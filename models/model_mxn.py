from models.basemodel import *


class model_mxn(ANBase):
    def __init__(self, opt):
        super(model_mxn, self).__init__(opt)

    def dataloader_setup(self):
        self.dataloader = {
            'gen': [load_data(self.opt) for _ in range(self.opt.n_MC_Gen)],
            'disc': [load_data(self.opt) for _ in range(self.opt.n_MC_Disc)]
        }

    def generator_setup(self):
        self.net_Gs = []
        self.optimizer_Gs = []
        for _idxmc in range(0, self.opt.n_MC_Gen):
            net_G = self.create_G(self.opt).to(self.device)
            # TODO: initialized weight with prior N(0, 0.02) [From bayesian GAN]
            net_G.apply(weights_init)
            optimizer_G = torch.optim.Adam(net_G.parameters(), lr=self.opt.lr, betas=(self.opt.beta1, 0.999))
            self.net_Gs.append(net_G)
            self.optimizer_Gs.append(optimizer_G)

    def discriminator_setup(self):
        self.net_Ds = []
        self.optimizer_Ds = []
        for _idxmc in range(0, self.opt.n_MC_Disc):
            net_D = self.create_D(self.opt).to(self.device)
            # TODO: initialized weight with prior N(0, 0.02) [From bayesian GAN]
            net_D.apply(weights_init)
            optimizer_D = torch.optim.Adam(net_D.parameters(), lr=self.opt.lr, betas=(self.opt.beta1, 0.999))
            self.net_Ds.append(net_D)
            self.optimizer_Ds.append(optimizer_D)

    def train_epoch(self, epoch):
        for _ in tqdm(range(len(self.dataloader["gen"][0].train)), leave=False,
                          total=len(self.dataloader["gen"][0].train)):
            self.global_iter += 1

            # TODO update each disc with all gens
            for _idxD in range(self.opt.n_MC_Disc):
                x_real, _ = next(iter(self.dataloader["disc"][_idxD].train))    # get data batch
                x_real = x_real.to(self.device)
                self.net_Ds[_idxD].zero_grad()
                label_real = torch.ones(x_real.shape[0]).to(self.device)        # create real label
                pred_real, feat_real = self.net_Ds[_idxD](x_real)               # get real prediction from network D
                err_d_real = self.l_adv(pred_real, label_real)

                err_d_fakes = 0.0
                err_d_lats = 0.0

                for _idxG in range(self.opt.n_MC_Gen):
                    x_fake = self.net_Gs[_idxG](x_real)                         # get fake image from network G
                    pred_fake, feat_fake = self.net_Ds[_idxD](x_fake.detach())  # get fake prediction from network D
                    label_fake = torch.zeros(x_real.shape[0]).to(self.device)

                    err_d_fake = self.l_adv(pred_fake, label_fake)
                    err_d_lat = self.l_lat(feat_real, feat_fake)

                    err_d_fakes += err_d_fake
                    err_d_lats += err_d_lat

                err_d_total_loss = err_d_fakes + err_d_lats + err_d_real * self.opt.n_MC_Gen

                err_d_total_loss /= self.opt.n_MC_Gen

                err_d_total_loss.backward()
                self.optims['disc'][_idxD].step()

            # TODO update each gen with all discs
            for _idxG in range(self.opt.n_MC_Gen):
                x_real, _ = next(iter(self.dataloader["gen"][_idxG].train))     # get data batch
                x_real = x_real.to(self.device)
                self.net_Gs[_idxG].zero_grad()
                x_fake = self.net_Gs[_idxG](x_real)                             # get fake image from network G
                err_g_con = self.l_con(x_real, x_fake)                          # get reconstruction loss

                err_g_fakes = 0.0

                for _idxD in range(self.opt.n_MC_Disc):
                    pred_fake, feat_fake = self.net_Ds[_idxD](x_fake)           # get fake prediction from network D
                    label_real = torch.ones(x_real.shape[0]).to(self.device)    # create inversed label

                    err_g_fake = self.l_adv(pred_fake, label_real)
                    err_g_fakes += err_g_fake

                err_g_total_loss = err_g_fakes * self.opt.n_MC_Disc + err_g_con
                err_g_total_loss /= self.opt.n_MC_Disc

                err_g_total_loss.backward()
                self.optims['gen'][_idxG].step()

    def compute_epoch(self, epoch, plot_hist=True):
        with torch.no_grad():
            self.opt.phase = 'test'

            means_test = torch.empty(
                size=(len(self.dataloader["gen"][0].train.dataset), self.opt.n_MC_Gen, self.opt.n_MC_Disc),
                dtype=torch.float32,
                device=self.device)

            gt_labels_test = torch.zeros(size=(len(self.dataloader["gen"][0].train.dataset),),
                                    dtype=torch.long, device=self.device)

            fake_latents_test = torch.empty(
                size=(len(self.dataloader["gen"][0].train.dataset), self.opt.n_MC_Gen, self.opt.n_MC_Disc, self.opt.nz),
                dtype=torch.float32,
                device=self.device)
            real_latents_test = torch.empty(
                size=(len(self.dataloader["gen"][0].train.dataset), self.opt.n_MC_Gen, self.opt.nz),
                dtype=torch.float32,
                device=self.device)
            for _idxData, (x_real, label) in enumerate(self.dataloader["gen"][0].train, 0):
                x_real = x_real.to(self.device)

                gt_labels_test[_idxData * self.opt.batchsize: _idxData * self.opt.batchsize + label.size(0)].copy_(label)
                for _idxD in range(self.opt.n_MC_Disc):
                    pred_real, feat_real = self.net_Ds[_idxD](x_real)
                    real_latents_test[_idxData * self.opt.batchsize:(_idxData + 1) * self.opt.batchsize, _idxD].copy_(feat_real.squeeze())
                    for _idxG in range(self.opt.n_MC_Gen):
                        x_fake = self.net_Gs[_idxG](x_real)
                        pred_fake, feat_fake = self.net_Ds[_idxD](x_fake)

                        fake_latents_test[_idxData * self.opt.batchsize:(_idxData + 1) * self.opt.batchsize, _idxG, _idxD].copy_(feat_fake.squeeze())
                        lat = (feat_real - feat_fake).view(feat_real.size()[0], -1)
                        # latents[_idxData * self.opt.batchsize:(_idxData + 1) * self.opt.batchsize, _idxG, _idxD].copy_(lat)

                        lat = torch.mean(torch.pow(lat, 2), dim=1)

                        means_test[_idxData * self.opt.batchsize:(_idxData + 1) * self.opt.batchsize, _idxG, _idxD].copy_(
                            lat)

            # fake_latents_test = torch.mean(fake_latents_test, dim=[1,2])
            # real_latents_test = torch.mean(real_latents_test, dim=1)
            # means_test= torch.mean(means_test, dim=[1, 2])

            means_test = means_test.cpu().numpy()
            fake_latents_test = fake_latents_test.cpu().numpy()
            real_latents_test = real_latents_test.cpu().numpy()

            scores = {}
            scores['mean'] = means_test
            scores['fake_latents'] = fake_latents_test
            scores['real_latents'] = real_latents_test
            scores['gt_labels'] = gt_labels_test.cpu().numpy()
            abnidx = self.dataloader["gen"][0].train.dataset.class_to_idx[self.opt.abnormal_class]
            import numpy as np
            np.save("{0}exp_{1}epoch_{2}abnidx_score_train.npy".format(self.opt.name, epoch, abnidx),scores)

            # if plot_hist:
            #     abnidx = self.dataloader["gen"][0].train.dataset.class_to_idx[self.opt.abnormal_class]
            #     plt.ion()
            #     # Create data frame for scores and labels.
            #     # scores = {}
            #     # scores['scores'] = means_train
            #     # scores['labels'] = gt_labels_train.cpu()
            #     # hist = pd.DataFrame.from_dict(scores)
            #     # hist.to_csv("{0}exp_{1}epoch_{2}abnidx_score_train.csv".format(self.opt.name, epoch, abnidx))
            #
            #     scores = {}
            #     scores['scores'] = means_test
            #     scores['labels'] = gt_labels_test.cpu()
            #     hist = pd.DataFrame.from_dict(scores)
            #     hist.to_csv("{0}exp_{1}epoch_{2}abnidx_score_test.csv".format(self.opt.name, epoch, abnidx))
            #
            # #     # Create data frame for scores and labels.
            #     hiddens = {}
            #     for dim in range(real_latents_test.shape[1]):
            #         hiddens['real_latent_%d'%dim] = real_latents_test[:, dim]
            #     hiddens['labels'] = gt_labels_test.cpu()
            #     hist = pd.DataFrame.from_dict(hiddens)
            #     hist.to_csv("{0}exp_{1}epoch_{2}abnidx_real_latent_test.csv".format(self.opt.name, epoch, abnidx))
            # #
            #     hiddens = {}
            #     for dim in range(fake_latents_test.shape[1]):
            #         hiddens['fake_latent_%d'%dim] = fake_latents_test[:, dim]
            #     hiddens['labels'] = gt_labels_test.cpu()
            #     hist = pd.DataFrame.from_dict(hiddens)
            #     hist.to_csv("{0}exp_{1}epoch_{2}abnidx_fake_latent_test.csv".format(self.opt.name, epoch, abnidx))

            #     plt.ion()
            #     # Create data frame for scores and labels.
            #     scores = {}
            #     scores['scores'] = means
            #     scores['labels'] = gt_labels.cpu()
            #     hist = pd.DataFrame.from_dict(scores)
            #     hist.to_csv("{0}/{1}/test/plots/mean_at_epoch{2}.csv".format(self.opt.outf, self.opt.name, epoch))

    def test_epoch(self, epoch, plot_hist=True):
        with torch.no_grad():
            self.opt.phase = 'test'
            means = torch.empty(
                size=(len(self.dataloader["gen"][0].valid.dataset), self.opt.n_MC_Gen, self.opt.n_MC_Disc),
                dtype=torch.float32,
                device=self.device)

            gt_labels = torch.zeros(size=(len(self.dataloader["gen"][0].valid.dataset),),
                                    dtype=torch.long, device=self.device)

            fake_latents = torch.empty(
                size=(len(self.dataloader["gen"][0].valid.dataset), self.opt.n_MC_Gen, self.opt.n_MC_Disc, self.opt.nz),
                dtype=torch.float32,
                device=self.device)
            real_latents = torch.empty(
                size=(len(self.dataloader["gen"][0].valid.dataset), self.opt.n_MC_Disc, self.opt.nz),
                dtype=torch.float32,
                device=self.device)
            for _idxData, (x_real, label) in enumerate(self.dataloader["gen"][0].valid, 0):
                x_real = x_real.to(self.device)

                gt_labels[_idxData * self.opt.batchsize: _idxData * self.opt.batchsize + label.size(0)].copy_(label)
                for _idxD in range(self.opt.n_MC_Disc):
                    pred_real, feat_real = self.net_Ds[_idxD](x_real)
                    real_latents[_idxData * self.opt.batchsize:(_idxData + 1) * self.opt.batchsize, _idxD].copy_(feat_real.squeeze())
                    for _idxG in range(self.opt.n_MC_Gen):
                        x_fake = self.net_Gs[_idxG](x_real)
                        pred_fake, feat_fake = self.net_Ds[_idxD](x_fake)

                        fake_latents[_idxData * self.opt.batchsize:(_idxData + 1) * self.opt.batchsize, _idxG, _idxD].copy_(feat_fake.squeeze())
                        lat = (feat_real - feat_fake).view(feat_real.size()[0], -1)
                        # latents[_idxData * self.opt.batchsize:(_idxData + 1) * self.opt.batchsize, _idxG, _idxD].copy_(lat)

                        lat = torch.mean(torch.pow(lat, 2), dim=1)

                        means[_idxData * self.opt.batchsize:(_idxData + 1) * self.opt.batchsize, _idxG, _idxD].copy_(
                            lat)

            means_D_based = torch.mean(means, dim=1, keepdim=True)

            means = torch.mean(means_D_based, dim=2)

            means = means.cpu().squeeze()
            if plot_hist:
                per_scores = means
                per_scores = (per_scores - torch.min(per_scores)) / (torch.max(per_scores) - torch.min(per_scores))
                roc(gt_labels, per_scores, epoch=epoch, save=os.path.join(self.opt.outf, self.opt.name,
                                                                                      "test/plots/mean_at_epoch{0}.png".format(
                                                                                          epoch)))
                # abnidx = self.dataloader["gen"][0].train.dataset.class_to_idx[self.opt.abnormal_class]
                plt.ion()
                # Create data frame for scores and labels.
                scores = {}
                scores['scores'] = means
                scores['labels'] = gt_labels.cpu()
                hist = pd.DataFrame.from_dict(scores)
                hist.to_csv(os.path.join(self.opt.outf, self.opt.name, "{0}exp_{1}epoch_score_train.csv".format(self.opt.name, epoch)))
